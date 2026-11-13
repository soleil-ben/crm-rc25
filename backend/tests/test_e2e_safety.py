"""The browser suite may write to one kind of database, and it must prove which one.

Every test here exists because of a single incident. On 2026-09-20 the Playwright suite ran
against ``data/solaris_crm.db`` and added 40 customers, 32 import batches, 36 import rows,
195 audit events and 11 user sessions to it. Nothing failed. Nothing warned. The suite
opened ``http://localhost:5173``, a development backend answered, and the staff specs wrote
into whatever database that backend was serving.

Two independent things now have to hold, and they are tested separately because each has to
hold on its own:

1. **A process running as the E2E backend cannot serve a real database.**
   ``app.core.e2e_guard`` refuses anything but an approved ``.e2e.db`` scratch file, and
   ``TestApprovedPaths`` / ``TestRefusedPaths`` walk every way of getting that wrong.
2. **The suite cannot reach a process it did not start.** ``app.api.e2e`` answers a
   handshake only when its own environment *and* the database it is serving both carry the
   caller's run identifier, and ``TestHandshake`` covers agreement, every disagreement, and
   absence.

And one negative, which is the part a reviewer should be most suspicious of:
``TestTheEndpointDoesNotExistElsewhere`` proves the handshake is not present in
development, production or under pytest -- not hidden, not disabled, *not routed*.

No test in this file opens the development database. ``TestNothingHereTouchesTheRealThing``
asserts that as a property rather than leaving it to review.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import config as config_module
from app.core import db as db_module
from app.core import e2e_guard
from app.core.config import Settings, database_path_problems
from app.core.db import build_engine
from app.main import E2E_PREFIX, create_app

REPO_ROOT = e2e_guard.REPO_ROOT
SCRIPTS = REPO_ROOT / "scripts"
RUN_ID = "0123456789abcdef0123456789abcdef"
OTHER_RUN_ID = "fedcba9876543210fedcba9876543210"


def url_for(path: Path | str) -> str:
    return f"sqlite:///{Path(path).as_posix()}"


def approved_database(run_id: str = RUN_ID) -> Path:
    """A path the guard must approve. Never created; only ever named.

    Spelled out here rather than taken from ``scripts/e2e_env.py`` on purpose: these tests
    are about what ``e2e_guard`` accepts, and deriving the input from the thing under
    test's own collaborator would make them agree with each other rather than with the
    rule. ``TestDestructiveTargetGuards`` uses the launcher's real layout, which is where
    the two are checked against one another.
    """
    return e2e_guard.E2E_DIR / f"run-{run_id}" / f"solaris{e2e_guard.E2E_DB_SUFFIX}"


# --- The path guard ------------------------------------------------------------------


class TestApprovedPaths:
    def test_the_shape_the_launcher_produces_is_approved(self):
        assert e2e_guard.e2e_database_problems(url_for(approved_database())) == []

    def test_a_nested_directory_under_the_run_is_approved(self):
        nested = e2e_guard.E2E_DIR / f"run-{RUN_ID}" / "nested" / f"other{e2e_guard.E2E_DB_SUFFIX}"
        assert e2e_guard.e2e_database_problems(url_for(nested)) == []

    def test_dot_segments_are_resolved_before_the_check(self):
        """``data/e2e/run-x/../run-x/solaris.e2e.db`` is the same file, and is approved."""
        awkward = e2e_guard.E2E_DIR / f"run-{RUN_ID}" / ".." / f"run-{RUN_ID}" / "solaris.e2e.db"
        assert e2e_guard.e2e_database_problems(url_for(awkward)) == []

    def test_the_roots_match_the_ones_config_computes(self):
        """`e2e_guard` recomputes them to break an import cycle; they must not drift."""
        assert e2e_guard.REPO_ROOT == config_module.REPO_ROOT
        assert e2e_guard.BACKEND_ROOT == config_module.BACKEND_ROOT


class TestRefusedPaths:
    """One test per way of naming the wrong file. Each must be refused on its own."""

    def test_the_development_database_is_refused(self):
        problems = e2e_guard.e2e_database_problems(url_for(e2e_guard.DEV_DB))
        assert problems
        assert any(".e2e.db" in problem for problem in problems)

    def test_the_development_database_is_still_refused_when_renamed_into_place(self):
        """Suffix alone is not the check: containment is checked too, and the reverse."""
        impostor = REPO_ROOT / "data" / f"solaris_crm{e2e_guard.E2E_DB_SUFFIX}"
        assert e2e_guard.e2e_database_problems(url_for(impostor))

    def test_the_uat_database_is_refused(self):
        uat = e2e_guard.UAT_DIR / "solaris_uat.uat.db"
        assert e2e_guard.e2e_database_problems(url_for(uat))

    def test_a_uat_path_carrying_the_e2e_suffix_is_still_refused(self):
        uat = e2e_guard.UAT_DIR / f"borrowed{e2e_guard.E2E_DB_SUFFIX}"
        problems = e2e_guard.e2e_database_problems(url_for(uat))
        assert any("UAT" in problem for problem in problems)

    def test_a_backup_is_refused(self):
        backup = e2e_guard.BACKUP_DIR / f"restored{e2e_guard.E2E_DB_SUFFIX}"
        problems = e2e_guard.e2e_database_problems(url_for(backup))
        assert any("backup" in problem for problem in problems)

    def test_a_production_style_absolute_path_elsewhere_is_refused(self):
        production = Path("/var/lib/solaris") / f"live{e2e_guard.E2E_DB_SUFFIX}"
        assert e2e_guard.e2e_database_problems(url_for(production))

    def test_the_source_tree_is_refused(self):
        inside = e2e_guard.BACKEND_ROOT / "app" / f"scratch{e2e_guard.E2E_DB_SUFFIX}"
        assert e2e_guard.e2e_database_problems(url_for(inside))

    def test_a_relative_path_is_refused(self):
        problems = e2e_guard.e2e_database_problems("sqlite:///data/e2e/run-x/solaris.e2e.db")
        assert any("absolute" in problem for problem in problems)

    def test_a_sibling_directory_with_a_shared_prefix_is_refused(self):
        """``data/e2e-scratch`` is a string prefix match and a different directory."""
        sibling = REPO_ROOT / "data" / "e2e-scratch" / f"a{e2e_guard.E2E_DB_SUFFIX}"
        assert e2e_guard.e2e_database_problems(url_for(sibling))

    def test_the_approved_directory_itself_is_refused(self):
        assert e2e_guard.e2e_database_problems(url_for(e2e_guard.E2E_DIR))

    def test_a_directory_target_is_refused(self, tmp_path):
        directory = e2e_guard.E2E_DIR / f"run-{RUN_ID}"
        problems = e2e_guard.e2e_database_problems(url_for(directory))
        assert problems

    def test_an_in_memory_database_is_refused(self):
        problems = e2e_guard.e2e_database_problems("sqlite:///:memory:")
        assert any("marker" in problem for problem in problems)

    def test_a_non_sqlite_url_is_refused(self):
        assert e2e_guard.e2e_database_problems("postgresql://localhost/solaris")

    def test_an_empty_url_is_refused(self):
        assert e2e_guard.e2e_database_problems("")

    def test_a_bare_db_suffix_is_refused(self):
        plain = e2e_guard.E2E_DIR / f"run-{RUN_ID}" / "solaris.db"
        problems = e2e_guard.e2e_database_problems(url_for(plain))
        assert any(".e2e.db" in problem for problem in problems)

    def test_a_suffix_in_the_middle_of_the_name_is_refused(self):
        sneaky = e2e_guard.E2E_DIR / f"run-{RUN_ID}" / "solaris.e2e.db.bak"
        assert e2e_guard.e2e_database_problems(url_for(sneaky))


@pytest.fixture
def reparse_point():
    """A real directory link inside ``data/e2e/`` that points at ``data/``.

    A *directory* link rather than a file symlink, because on Windows a file symlink needs
    a privilege an ordinary account does not have while a junction needs none -- so this
    exercises reparse-point resolution for real on both platforms instead of skipping on
    one of them. Everything reached through it lives outside the approved directory, which
    is the escape the guard has to resolve before it checks containment.
    """
    e2e_guard.E2E_DIR.mkdir(parents=True, exist_ok=True)
    link = e2e_guard.E2E_DIR / f"link-{os.getpid()}"
    target = REPO_ROOT / "data"
    if link.exists():
        link.rmdir() if not link.is_symlink() else link.unlink()
    if os.name == "nt":
        result = subprocess.run(  # noqa: S603
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"could not create a junction: {result.stderr}"
    else:
        link.symlink_to(target, target_is_directory=True)
    try:
        yield link
    finally:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)  # noqa: S603
        else:
            link.unlink()


class TestReparsePointEscape:
    """A link inside the approved directory that points outside it is still outside it."""

    def test_the_development_database_reached_through_a_junction_is_refused(self, reparse_point):
        through = reparse_point / "solaris_crm.db"
        assert e2e_guard.canonical(through) == e2e_guard.canonical(e2e_guard.DEV_DB)
        problems = e2e_guard.e2e_database_problems(url_for(through))
        assert problems, "a link resolving to the development database was approved"

    def test_a_scratch_name_reached_through_a_junction_is_still_refused(self, reparse_point):
        """The suffix is satisfied and the literal path starts inside. It is still outside."""
        through = reparse_point / f"borrowed{e2e_guard.E2E_DB_SUFFIX}"
        problems = e2e_guard.e2e_database_problems(url_for(through))
        assert any("outside" in problem for problem in problems)

    def test_the_uat_database_reached_through_a_junction_is_refused(self, reparse_point):
        through = reparse_point / "uat" / f"borrowed{e2e_guard.E2E_DB_SUFFIX}"
        assert e2e_guard.e2e_database_problems(url_for(through))

    def test_a_link_that_lands_back_inside_the_approved_directory_is_approved(self, reparse_point):
        """The check is on where a path *resolves*, not on how it was spelt."""
        through = reparse_point / "e2e" / f"run-{RUN_ID}" / "solaris.e2e.db"
        assert e2e_guard.e2e_database_problems(url_for(through)) == []

    def test_a_relative_traversal_out_of_the_approved_directory_is_refused(self):
        escape = e2e_guard.E2E_DIR / ".." / "solaris_crm.db"
        assert e2e_guard.e2e_database_problems(url_for(escape))

    def test_a_traversal_that_lands_back_inside_is_approved(self):
        back = e2e_guard.E2E_DIR / ".." / "e2e" / f"run-{RUN_ID}" / "solaris.e2e.db"
        assert e2e_guard.e2e_database_problems(url_for(back)) == []


class TestWindowsPathNormalisation:
    def test_case_follows_the_platform(self):
        """Upper case is the same file on Windows and a different one on POSIX."""
        shouty = Path(str(approved_database()).upper())
        problems = e2e_guard.e2e_database_problems(url_for(shouty))
        if os.name == "nt":
            assert problems == []
        else:
            assert problems

    def test_forward_and_backward_slashes_name_the_same_file(self):
        posix = url_for(approved_database())
        native = f"sqlite:///{approved_database()!s}"
        assert e2e_guard.e2e_database_problems(posix) == e2e_guard.e2e_database_problems(native)

    def test_a_windows_short_name_style_segment_does_not_slip_past_containment(self):
        """Anything that resolves outside the approved directory is refused, however spelt."""
        assert e2e_guard.e2e_database_problems(url_for(REPO_ROOT / "PROGRA~1" / "a.e2e.db"))


class TestRunIdentifier:
    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_absence_is_refused(self, value):
        problems = e2e_guard.run_id_problems(value)
        assert any(e2e_guard.RUN_ID_ENV_VAR in problem for problem in problems)

    @pytest.mark.parametrize(
        "value",
        [
            "not-hex",
            "0123456789ABCDEF0123456789ABCDEF",  # upper case
            "0123456789abcdef",  # too short
            "0123456789abcdef0123456789abcdef0",  # too long
            "0123456789abcdef0123456789abcde;",  # shell metacharacter
            "../../etc/passwd",
        ],
    )
    def test_a_malformed_identifier_is_refused(self, value):
        assert e2e_guard.run_id_problems(value)

    def test_a_well_formed_identifier_is_accepted(self):
        assert e2e_guard.run_id_problems(RUN_ID) == []

    def test_startup_reports_both_kinds_of_problem_at_once(self):
        problems = e2e_guard.e2e_startup_problems(url_for(e2e_guard.DEV_DB), None)
        assert len(problems) >= 2


# --- Startup refusals ------------------------------------------------------------------


class TestStartupRefusals:
    """`get_settings` must refuse rather than serve. Built directly, not through the cache."""

    def _settings(self, **overrides) -> Settings:
        return Settings(**overrides)

    def test_an_e2e_backend_refuses_the_development_database(self):
        problems = e2e_guard.e2e_startup_problems(url_for(e2e_guard.DEV_DB), RUN_ID)
        assert problems

    def test_an_e2e_backend_refuses_the_uat_database(self):
        uat = e2e_guard.UAT_DIR / "solaris_uat.uat.db"
        assert e2e_guard.e2e_startup_problems(url_for(uat), RUN_ID)

    def test_an_e2e_backend_refuses_to_start_without_a_run_identifier(self):
        assert e2e_guard.e2e_startup_problems(url_for(approved_database()), None)

    def test_an_e2e_backend_accepts_an_approved_database_and_identifier(self):
        assert e2e_guard.e2e_startup_problems(url_for(approved_database()), RUN_ID) == []

    def test_production_refuses_a_scratch_database(self):
        """The guard in the other direction: a real deployment must not serve an .e2e.db."""
        settings = self._settings(
            environment="production", database_url=url_for(approved_database())
        )
        problems = database_path_problems(settings)
        assert any(".e2e.db" in problem for problem in problems)

    def test_production_still_accepts_an_ordinary_absolute_database(self, tmp_path):
        settings = self._settings(
            environment="production", database_url=url_for(tmp_path / "solaris.db")
        )
        assert database_path_problems(settings) == []

    def test_no_production_or_development_default_moved(self):
        """The E2E limits are applied by the harness, never written into the defaults.

        The *field defaults* rather than a constructed ``Settings``: the test process
        exports ``ENVIRONMENT=test``, and a constructed instance would report that
        rather than what the application ships with.
        """
        fields = Settings.model_fields
        assert fields["public_tracking_rate_limit_attempts"].default == 30
        assert fields["login_rate_limit_attempts"].default == 8
        assert fields["environment"].default == "development"
        assert fields["trust_proxy_headers"].default is False


# --- The handshake ----------------------------------------------------------------------


@pytest.fixture
def e2e_app(monkeypatch, tmp_path):
    """An application built as the E2E backend, with its own marked scratch database.

    The database lives in ``tmp_path`` rather than in ``data/e2e/``: the handshake reads
    whatever engine it is given and the path guard is tested separately, so putting a real
    file under the approved directory would only add a stray artifact to the repository.
    """

    def build(*, environment: str = "e2e", process_run_id=RUN_ID, database_run_id=RUN_ID):
        scratch = tmp_path / f"solaris{e2e_guard.E2E_DB_SUFFIX}"
        engine = build_engine(url_for(scratch))
        if database_run_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        f"CREATE TABLE IF NOT EXISTS {e2e_guard.RUN_MARKER_TABLE} "
                        "(run_id TEXT NOT NULL, created_at TEXT NOT NULL)"
                    )
                )
                connection.execute(
                    text(
                        f"INSERT INTO {e2e_guard.RUN_MARKER_TABLE} (run_id, created_at) "
                        "VALUES (:run_id, 'now')"
                    ),
                    {"run_id": database_run_id},
                )
        monkeypatch.setattr(db_module, "engine", engine)
        monkeypatch.setattr(config_module.settings, "environment", environment)
        if process_run_id is None:
            monkeypatch.delenv(e2e_guard.RUN_ID_ENV_VAR, raising=False)
        else:
            monkeypatch.setenv(e2e_guard.RUN_ID_ENV_VAR, process_run_id)
        return TestClient(create_app())

    return build


def handshake(client: TestClient, run_id: str | None):
    headers = {"X-E2E-Run-Id": run_id} if run_id is not None else {}
    return client.get(f"{E2E_PREFIX}/handshake", headers=headers)


class TestHandshake:
    def test_the_right_process_and_the_right_database_agree(self, e2e_app):
        response = handshake(e2e_app(), RUN_ID)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_a_stale_backend_from_an_earlier_run_is_refused(self, e2e_app):
        """Same code, same port, different run. This is the case a port check cannot see."""
        client = e2e_app(process_run_id=OTHER_RUN_ID, database_run_id=OTHER_RUN_ID)
        assert handshake(client, RUN_ID).status_code == 409

    def test_the_right_process_serving_the_wrong_database_is_refused(self, e2e_app):
        client = e2e_app(process_run_id=RUN_ID, database_run_id=OTHER_RUN_ID)
        assert handshake(client, RUN_ID).status_code == 409

    def test_a_database_with_no_marker_is_refused(self, e2e_app):
        client = e2e_app(process_run_id=RUN_ID, database_run_id=None)
        assert handshake(client, RUN_ID).status_code == 409

    def test_a_process_with_no_run_identifier_is_refused(self, e2e_app):
        client = e2e_app(process_run_id=None)
        assert handshake(client, RUN_ID).status_code == 409

    def test_a_caller_that_presents_nothing_is_refused(self, e2e_app):
        assert handshake(e2e_app(), None).status_code == 409

    def test_an_empty_identifier_is_refused(self, e2e_app):
        assert handshake(e2e_app(), "").status_code == 409

    def test_the_refusal_says_nothing_but_that_it_refused(self, e2e_app):
        """No path, no revision, no counts, and never the identifier it expected."""
        client = e2e_app(process_run_id=OTHER_RUN_ID, database_run_id=OTHER_RUN_ID)
        body = handshake(client, RUN_ID).text
        assert body == '{"status":"mismatch"}'
        assert OTHER_RUN_ID not in body

    def test_success_says_nothing_but_that_it_succeeded(self, e2e_app):
        body = handshake(e2e_app(), RUN_ID).text
        assert body == '{"status":"ok"}'

    def test_it_grants_nothing(self, e2e_app):
        """The identifier is not a credential: a correct one opens no staff route."""
        client = e2e_app()
        response = client.get("/api/v1/customers", headers={"X-E2E-Run-Id": RUN_ID})
        assert response.status_code in (401, 403)

    def test_it_sets_no_cookie(self, e2e_app):
        client = e2e_app()
        response = handshake(client, RUN_ID)
        assert not response.cookies


class TestTheEndpointDoesNotExistElsewhere:
    """Not hidden, not disabled -- never routed. The strongest form of the claim."""

    @pytest.mark.parametrize("environment", ["development", "production", "test", "uat", "prod"])
    def test_the_route_is_absent(self, e2e_app, environment):
        client = e2e_app(environment=environment)
        assert handshake(client, RUN_ID).status_code == 404

    @pytest.mark.parametrize("environment", ["development", "production", "test"])
    def test_no_e2e_path_is_in_the_route_table(self, monkeypatch, environment):
        monkeypatch.setattr(config_module.settings, "environment", environment)
        paths = [getattr(route, "path", "") for route in create_app().routes]
        assert not [path for path in paths if "e2e" in path.lower()]

    def test_it_is_absent_from_the_openapi_document_in_development(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "environment", "development")
        document = create_app().openapi()
        assert not [path for path in document["paths"] if "e2e" in path.lower()]

    def test_it_is_absent_from_the_openapi_document_even_when_it_is_mounted(self, e2e_app):
        """`include_in_schema=False`, so even the E2E process does not advertise it."""
        client = e2e_app()
        document = client.app.openapi()
        assert not [path for path in document["paths"] if "e2e" in path.lower()]


# --- The destructive-target guards in scripts/e2e_env.py ---------------------------------


def run_e2e_env(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the reset/cleanup helper as an operator would, and report what it said."""
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "e2e_env.py"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


@pytest.fixture(scope="module")
def e2e_env_module():
    """`scripts/e2e_env.py` imported directly, so its guards can be called as functions."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        import e2e_env  # noqa: PLC0415

        return e2e_env
    finally:
        sys.path.remove(str(SCRIPTS))


class TestDestructiveTargetGuards:
    """Every refusal, proven by asking the helper to do the wrong thing.

    These are mutation tests in the sense that matters: each one names a target that a
    guard is the only thing standing between, and asserts a refusal rather than an
    outcome. If a guard is deleted, exactly one of these fails and names it.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "solaris_crm.db",  # the development database
            "solaris.db",
            "solaris.uat.db",
            "solaris.e2e.db.bak",
        ],
    )
    def test_a_target_without_the_approved_suffix_is_refused(self, e2e_env_module, name):
        target = e2e_guard.E2E_DIR / f"run-{RUN_ID}" / name
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_target(target)

    def test_the_development_database_is_refused(self, e2e_env_module):
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_target(e2e_guard.DEV_DB)

    def test_the_uat_database_is_refused(self, e2e_env_module):
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_target(e2e_guard.UAT_DIR / "solaris_uat.uat.db")

    def test_a_backup_directory_target_is_refused(self, e2e_env_module):
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_target(e2e_guard.BACKUP_DIR / "anything.e2e.db")

    def test_a_directory_is_refused(self, e2e_env_module):
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_target(e2e_guard.E2E_DIR)

    def test_a_path_outside_the_approved_directory_is_refused(self, e2e_env_module, tmp_path):
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_target(tmp_path / "solaris.e2e.db")

    # `monkeypatch` rather than setting `os.environ` and putting it back by hand. The
    # hand-rolled version of the second test here restored `DATABASE_URL` by *deleting* it,
    # which was correct while nothing set it and became test pollution the moment
    # `conftest.py` did -- it silently unset the variable for every test that ran
    # afterwards. `test_no_suite_opens_the_development_database.py` is what caught it.

    def test_a_production_environment_is_refused_before_any_path_check(
        self, e2e_env_module, monkeypatch
    ):
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_target(approved_database())

    def test_the_currently_configured_database_is_refused_as_a_target(
        self, e2e_env_module, monkeypatch
    ):
        """A shell exporting the development database cannot have it reused as a target."""
        target = approved_database()
        monkeypatch.setenv("DATABASE_URL", url_for(target))
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_target(target)

    def test_an_approved_target_passes(self, e2e_env_module):
        assert e2e_env_module.validated_target(approved_database())

    def test_the_launchers_own_layout_passes_the_guard(self, e2e_env_module):
        """The two agree: what `e2e_env.py` builds is what `e2e_guard` approves.

        The one test here that deliberately does *not* construct its own path. If the run
        directory is ever renamed -- it was shortened once already, to stay inside Windows
        `MAX_PATH` -- this is what catches a layout the guard would refuse.
        """
        target = e2e_env_module.database_path(RUN_ID)
        assert e2e_guard.e2e_database_problems(url_for(target)) == []
        assert e2e_env_module.validated_target(target) == e2e_guard.canonical(target)
        assert e2e_guard.is_within(
            e2e_guard.canonical(e2e_env_module.artifacts_directory(RUN_ID)),
            e2e_guard.canonical(e2e_guard.E2E_DIR),
        )

    @pytest.mark.parametrize(
        "run_id", ["", "not-hex", "../../data", "0123456789abcdef", "0" * 33, "A" * 32]
    )
    def test_a_malformed_run_identifier_cannot_name_a_directory(self, e2e_env_module, run_id):
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.run_directory(run_id)

    def test_the_approved_root_itself_cannot_be_destroyed(self, e2e_env_module, monkeypatch):
        """`--destroy` removes one run, never the root, however it is asked."""
        monkeypatch.setattr(e2e_env_module, "run_directory", lambda _: e2e_guard.E2E_DIR)
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_run_directory(RUN_ID)

    def test_a_grandchild_directory_cannot_be_destroyed(self, e2e_env_module, monkeypatch):
        """Only a direct child of the approved root. A deeper path is a different shape."""
        deep = e2e_env_module.artifacts_directory(RUN_ID)
        monkeypatch.setattr(e2e_env_module, "run_directory", lambda _: deep)
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_run_directory(RUN_ID)

    def test_a_directory_outside_the_root_cannot_be_destroyed(
        self, e2e_env_module, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(e2e_env_module, "run_directory", lambda _: tmp_path)
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_run_directory(RUN_ID)

    def test_the_repository_root_cannot_be_destroyed(self, e2e_env_module, monkeypatch):
        monkeypatch.setattr(e2e_env_module, "run_directory", lambda _: REPO_ROOT)
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_run_directory(RUN_ID)

    def test_the_backup_directory_cannot_be_destroyed(self, e2e_env_module, monkeypatch):
        monkeypatch.setattr(e2e_env_module, "run_directory", lambda _: e2e_guard.BACKUP_DIR)
        with pytest.raises(e2e_env_module.SafetyError):
            e2e_env_module.validated_run_directory(RUN_ID)

    def test_a_run_directory_is_approved(self, e2e_env_module):
        assert e2e_env_module.validated_run_directory(RUN_ID)


class TestCleanupTouchesOnlyThisRun:
    def test_destroy_removes_its_own_directory_and_leaves_its_neighbours(
        self, e2e_env_module, monkeypatch
    ):
        mine = e2e_env_module.run_directory(RUN_ID)
        theirs = e2e_env_module.run_directory(OTHER_RUN_ID)
        (mine / "artifacts").mkdir(parents=True, exist_ok=True)
        (mine / f"solaris{e2e_guard.E2E_DB_SUFFIX}").write_bytes(b"")
        theirs.mkdir(parents=True, exist_ok=True)
        (theirs / "evidence.txt").write_text("a failed run's preserved output", encoding="utf-8")
        try:
            e2e_env_module.destroy(RUN_ID, quiet=True)
            assert not mine.exists()
            assert theirs.exists(), "another run's preserved evidence was removed"
            assert (theirs / "evidence.txt").exists()
        finally:
            for path in (mine, theirs):
                if path.exists():
                    import shutil  # noqa: PLC0415

                    shutil.rmtree(path)

    def test_destroying_a_run_that_never_existed_is_not_an_error(self, e2e_env_module):
        e2e_env_module.destroy(OTHER_RUN_ID, quiet=True)


class TestTheDocumentedRateLimits:
    def test_the_backend_environment_carries_them_without_being_asked(self, e2e_env_module):
        environment = e2e_env_module.backend_environment(RUN_ID)
        assert environment["PUBLIC_TRACKING_RATE_LIMIT_ATTEMPTS"] == "200"
        assert environment["LOGIN_RATE_LIMIT_ATTEMPTS"] == "100"

    def test_the_backend_environment_carries_the_run_identifier_and_the_environment(
        self, e2e_env_module
    ):
        environment = e2e_env_module.backend_environment(RUN_ID)
        assert environment["ENVIRONMENT"] == e2e_guard.E2E_ENVIRONMENT
        assert environment[e2e_guard.RUN_ID_ENV_VAR] == RUN_ID
        assert environment["DATABASE_URL"].endswith(f"solaris{e2e_guard.E2E_DB_SUFFIX}")

    def test_proxy_headers_stay_disabled(self, e2e_env_module):
        """DEC-0048. A believed forwarding header lets a test pick its own limiter bucket."""
        environment = e2e_env_module.backend_environment(RUN_ID)
        assert environment["TRUST_PROXY_HEADERS"] == "false"
        assert environment["TRUSTED_PROXY_HOSTS"] == ""

    def test_two_runs_get_different_databases(self, e2e_env_module):
        """Sequential suites share no database, so no state carries from one to the next."""
        first = e2e_env_module.backend_environment(RUN_ID)["DATABASE_URL"]
        second = e2e_env_module.backend_environment(OTHER_RUN_ID)["DATABASE_URL"]
        assert first != second

    def test_a_fresh_run_identifier_is_never_reused(self, e2e_env_module):
        identifiers = {e2e_env_module.new_run_id() for _ in range(50)}
        assert len(identifiers) == 50
        assert all(e2e_guard.run_id_problems(value) == [] for value in identifiers)


class TestTheCapturedMailStaysInsideTheRun:
    """Phase 12. The suite needs real verification links; nothing else may reach them."""

    def test_the_capture_transport_is_selected_rather_than_the_null_one(self, e2e_env_module):
        """`null` records that a send was requested and produces nothing to read, which is
        the right default for pytest and useless for a browser journey that has to follow
        a verification link."""
        environment = e2e_env_module.backend_environment(RUN_ID)
        assert environment["ACCOUNT_EMAIL_TRANSPORT"] == "capture"

    def test_the_capture_directory_is_inside_this_runs_own_directory(self, e2e_env_module):
        """So it is removed with a passing run and preserved with a failing one, and so
        two runs cannot read each other's tokens."""
        environment = e2e_env_module.backend_environment(RUN_ID)
        capture = Path(environment["ACCOUNT_EMAIL_CAPTURE_DIR"])
        assert e2e_guard.is_within(
            e2e_guard.canonical(capture), e2e_guard.canonical(e2e_env_module.run_directory(RUN_ID))
        )

    def test_the_capture_directory_is_inside_the_git_ignored_e2e_root(self, e2e_env_module):
        """A captured message carries a live credential. `data/e2e/` is ignored at any
        depth, so one cannot be committed even by accident."""
        capture = Path(e2e_env_module.backend_environment(RUN_ID)["ACCOUNT_EMAIL_CAPTURE_DIR"])
        assert e2e_guard.is_within(
            e2e_guard.canonical(capture), e2e_guard.canonical(e2e_guard.E2E_DIR)
        )

    def test_it_is_never_the_development_capture_directory(self, e2e_env_module):
        """The one path this must not be. A run writing into `data/account_mail/` would
        mix synthetic tokens into the directory a developer reads by hand."""
        capture = Path(e2e_env_module.backend_environment(RUN_ID)["ACCOUNT_EMAIL_CAPTURE_DIR"])
        development = e2e_guard.REPO_ROOT / "data" / "account_mail"
        assert e2e_guard.canonical(capture) != e2e_guard.canonical(development)

    def test_two_runs_capture_into_different_directories(self, e2e_env_module):
        first = e2e_env_module.backend_environment(RUN_ID)["ACCOUNT_EMAIL_CAPTURE_DIR"]
        second = e2e_env_module.backend_environment(OTHER_RUN_ID)["ACCOUNT_EMAIL_CAPTURE_DIR"]
        assert first != second

    def test_the_destroy_path_removes_the_captured_mail_with_the_run(self, e2e_env_module):
        """Not a separate cleanup step. The capture lives under the run directory, so the
        existing `--destroy` removes it, and a forgotten second step cannot leave tokens
        behind."""
        capture = Path(e2e_env_module.backend_environment(RUN_ID)["ACCOUNT_EMAIL_CAPTURE_DIR"])
        assert capture.parent == e2e_env_module.run_directory(RUN_ID)


class TestTheHelperRefusesFromTheCommandLine:
    """The guards hold when the script is invoked the way a person would invoke it."""

    def test_a_malformed_run_identifier_exits_two(self):
        result = run_e2e_env("--destroy", "--run-id", "../../data")
        assert result.returncode == 2
        assert "Refused" in result.stderr

    def test_a_missing_run_identifier_exits_two(self):
        result = run_e2e_env("--destroy", env={e2e_guard.RUN_ID_ENV_VAR: ""})
        assert result.returncode == 2

    def test_production_is_refused(self):
        result = run_e2e_env("--destroy", "--run-id", RUN_ID, env={"ENVIRONMENT": "production"})
        assert result.returncode == 2
        assert "production" in result.stderr

    def test_a_new_run_identifier_is_well_formed(self):
        result = run_e2e_env("--new-run-id")
        assert result.returncode == 0
        assert e2e_guard.run_id_problems(result.stdout.strip()) == []


class TestNothingHereTouchesTheRealThing:
    """The property the whole file is about, asserted rather than assumed."""

    def test_no_test_in_this_module_opened_the_development_database(self):
        """The file's own mtime is the evidence: reading it would not change it, and
        writing to it is what this work exists to prevent. Recorded at import and
        compared here, so a test that opened it for writing is caught by the assertion
        rather than by somebody noticing later.

        Holds whether or not a development database exists: a fresh worktree has none,
        and then the property is that none was created. Requiring one made this test
        fail in every worktree for a reason that had nothing to do with safety."""
        assert _mtime_or_none(e2e_guard.DEV_DB) == _DEV_DB_MTIME_AT_IMPORT

    def test_no_test_in_this_module_opened_the_uat_database(self):
        """Holds whether or not a UAT database is built: absent then, absent now."""
        uat = e2e_guard.UAT_DIR / "solaris_uat.uat.db"
        assert _mtime_or_none(uat) == _UAT_DB_MTIME_AT_IMPORT


def _mtime_or_none(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


_DEV_DB_MTIME_AT_IMPORT = _mtime_or_none(e2e_guard.DEV_DB)
_UAT_DB_MTIME_AT_IMPORT = _mtime_or_none(e2e_guard.UAT_DIR / "solaris_uat.uat.db")
