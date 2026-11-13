"""FastAPI application factory.

Two surfaces share one process and share nothing else.

``/api/v1/...`` is the **staff API**: a server-managed session in an HTTP-only cookie, a
CSRF token echoed on every state-changing request, and a permission check on every data
route.

``/api/v1/public/...`` is the **public tracking API**, added in Phase 3. It has no
session, no CSRF, no permission matrix, and its own explicit safe response models. It is
mounted as its own router rather than as a prefix inside the staff router, so the
separation is visible in the route table and in the OpenAPI document rather than resting
on a reviewer noticing a missing dependency.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.account.router import account_router
from app.api.account.shipments import ACCOUNT_HEADERS
from app.api.e2e import router as e2e_router
from app.api.public.router import public_router
from app.api.public.tracking import PUBLIC_HEADERS
from app.api.v1.router import api_router
from app.core import e2e_guard
from app.core.config import configuration_warnings, settings
from app.core.logging import (
    accept_correlation_id,
    configure_logging,
    current_correlation_id,
    log_event,
    reset_correlation_id,
    set_correlation_id,
)
from app.core.time_utils import is_known_timezone
from app.services.errors import DomainError, RateLimitedError

logger = logging.getLogger("solaris.crm")

#: Echoed on every *staff* response, and present on every log record for the request.
#: Deliberately absent from public responses -- see `_attach_correlation` (DEC-0085).
CORRELATION_HEADER = "X-Correlation-ID"

#: Everything under this prefix is unauthenticated and customer-facing.
PUBLIC_PREFIX = f"{settings.api_v1_prefix}/public"

#: Everything under this prefix is the Customer Account: authenticated, but authenticated
#: as somebody who is not staff. It shares no cookie, no session table, no dependency and
#: no response schema with the staff API (DEC-0090). Its failures use the narrow public
#: error shape rather than the staff one, for the reason DEC-0051 gives: a `field` or a
#: `detail` that varied between two refusals would be the thing that told them apart.
ACCOUNT_PREFIX = f"{settings.api_v1_prefix}/account"
#: The Phase 11 read routes, which carry the fuller authenticated privacy header set.
ACCOUNT_SHIPMENTS_PREFIX = f"{ACCOUNT_PREFIX}/shipments"
#: The routes that return a customer's own data carry that set too: the shipment routes,
#: and since fix pack 2 the profile and marketing-consent routes.
ACCOUNT_PRIVATE_PREFIXES = (
    ACCOUNT_SHIPMENTS_PREFIX,
    f"{ACCOUNT_PREFIX}/profile",
    f"{ACCOUNT_PREFIX}/consent",
)

#: The end-to-end handshake, mounted only when `ENVIRONMENT` is `e2e` (`app.api.e2e`).
#: The constant is defined unconditionally so a test can assert the path is *absent* by
#: name in every other environment.
E2E_PREFIX = f"{settings.api_v1_prefix}/e2e"

DESCRIPTION = """
Internal staff API for the Solaris Express CRM portal.

Authentication uses a server-managed session in an HTTP-only cookie plus a CSRF token
echoed in the `X-CSRF-Token` header on every state-changing request. Authorization is
enforced per route from the role permission matrix.
""".strip()


def _verify_timezone_database() -> None:
    """Fail at startup rather than mislabel timestamps at runtime.

    Windows ships no system timezone database and slim Linux images often omit one. When
    ``zoneinfo`` cannot resolve the configured office timezone, every "Toronto" timestamp
    and every report period boundary would otherwise be UTC while still being labelled
    Toronto — wrong in a way nobody reading the report could see. ``tzdata`` is a declared
    dependency; this check turns a missing one into an actionable message.
    """
    if not is_known_timezone(settings.default_timezone):
        raise RuntimeError(
            f"The configured timezone {settings.default_timezone!r} cannot be resolved. "
            "Install the 'tzdata' package (it is a declared dependency) or set "
            "DEFAULT_TIMEZONE to a name this installation knows."
        )


def _route_template(request: Request) -> str:
    """The matched route's template, or `unmatched`. Never the resolved path."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


def _attach_correlation(request: Request, response: Response) -> None:
    """Echo the correlation id -- on the staff API only (DEC-0085, extended in Phase 9).

    The public surface is required to answer every failure identically. A header that
    differs per request would be the one thing telling two otherwise identical 404s
    apart, which is precisely the distinction DEC-0051 exists to deny. The id is still
    logged for every public request; it is simply not returned to the caller.

    **The Customer Account is held to the same rule**, and for a sharper reason: its
    registration, resend and password-reset responses must be byte-identical whether or not
    an address has an account, and a per-request header is by definition a value that
    differs between two responses. Correlation for staff APIs is preserved -- the id is
    generated, is on every log record for the request, and is how an operator joins a
    customer's report to the logs. It is simply not handed to the customer, and no public
    correlation header is added to keep the two boundaries the same (instruction section 14).
    """
    if request.url.path.startswith((PUBLIC_PREFIX, ACCOUNT_PREFIX)):
        return
    response.headers[CORRELATION_HEADER] = current_correlation_id() or ""


def _check_database_reachable() -> bool:
    """One cheap query. Readiness means "can serve", and serving needs the database."""
    from sqlalchemy import text

    from app.core.db import engine

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        # Deliberately not logged with the exception: a driver's message carries the
        # connection string, which carries the path. The readiness event records the
        # failing check by name and nothing else.
        return False
    return True


def _check_migrations_current() -> bool:
    """The schema the code expects is the schema the database has.

    Serving against a database that has not been migrated produces errors that look like
    application bugs. Readiness is where that is caught, before traffic arrives.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text

    from app.core.config import BACKEND_ROOT
    from app.core.db import engine

    try:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        expected = set(ScriptDirectory.from_config(config).get_heads())
        with engine.connect() as connection:
            if "alembic_version" not in inspect(connection).get_table_names():
                return False
            rows = connection.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        return {row[0] for row in rows} == expected
    except Exception:
        return False


def _refuse_demo_accounts_in_production(db=None) -> None:
    """A production database must not hold a usable demo or UAT account.

    The seed already refuses to run in production, so this is not about seeding. It is
    about the copy: a database created and seeded in development, then promoted or
    restored into production, arrives carrying five accounts whose password is printed in
    the seed output and committed to the documentation. Nothing downstream of that would
    have noticed.

    So the application refuses to start. Not a warning -- `config.py` draws the line at
    "refuse what is unsafe, warn about what is merely incomplete", and known credentials
    on a production system is the first kind. The refusal names every offending address,
    because an operator fixing this needs the list, and these addresses are reserved
    names that belong to nobody (`app.core.demo_identity`).

    Deactivated accounts are ignored: `is_active = false` already refuses the login, and
    keeping a deactivated demo row is a legitimate way to preserve history.

    `db` is for the tests, which hold their own session against a temporary database. In
    the running application it is None and this opens its own.
    """
    if not settings.is_production:
        return

    from sqlalchemy import select

    from app.core.db import session_scope
    from app.core.demo_identity import is_reserved_demo_email
    from app.models import User

    def offending(session) -> list[str]:
        return sorted(
            user.email
            for user in session.scalars(select(User).where(User.is_active.is_(True)))
            if is_reserved_demo_email(user.email)
        )

    if db is not None:
        offenders = offending(db)
    else:
        with session_scope() as session:
            offenders = offending(session)

    if offenders:
        listed = "\n".join(f"  - {email}" for email in offenders)
        raise RuntimeError(
            f"Refusing to start: {len(offenders)} demo or UAT account(s) are active in a "
            f"production database.\n{listed}\n"
            "These are seeded identities on reserved domains and their password is public. "
            "Deactivate or remove them before serving production traffic."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown, both of them observable.

    Shutdown is a plain, logged exit. There is no in-request background work to drain:
    the integration worker is a separate process with its own signal handling
    (`docs/OPERATIONS.md` section 9), and label PDFs are generated and streamed inside
    the request that asked for them. Uvicorn already waits for in-flight requests to
    finish before closing, so "safe shutdown" here means saying so rather than adding a
    drain loop that would have nothing to drain.
    """
    _refuse_demo_accounts_in_production()
    for warning in configuration_warnings(settings):
        log_event(logger, logging.WARNING, "configuration_incomplete", reason_code=warning)
    log_event(
        logger,
        logging.INFO,
        "startup_complete",
        environment=settings.environment,
        ready=_check_database_reachable() and _check_migrations_current(),
    )
    try:
        yield
    finally:
        log_event(logger, logging.INFO, "shutdown_complete", environment=settings.environment)


def create_app() -> FastAPI:
    _verify_timezone_database()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        description=DESCRIPTION,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url=f"{settings.api_v1_prefix}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # CORS is restricted to the configured frontend origins and must allow credentials
    # so the session cookie is sent (CRM.md section 3).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            settings.csrf_header_name,
            settings.account_csrf_header_name,
        ],
        max_age=600,
    )

    @app.middleware("http")
    async def correlate_and_log(request: Request, call_next):
        """Assign a correlation id, bound the body, time the request, log the outcome.

        **The route template is logged, never the resolved path.** A public tracking
        request is `/api/v1/public/track/SX-CAV-XXXXXXXX`, and the reference in that path
        is exactly what `CRM.md` section 10 and DEC-0057 forbid writing down. FastAPI
        records the matched route on the scope during routing, so the template is
        available by the time the response comes back; a request that matched nothing has
        no template and is logged as `unmatched` rather than by its path.

        **The correlation id is not echoed on a public response** (DEC-0085). Every
        public failure is required to be byte-identical to every other -- same status,
        same body, same headers -- so that an unknown reference and a cancelled shipment
        cannot be told apart by a stranger probing identifiers (DEC-0051). A per-request
        header is by definition a value that differs between two responses, and adding it
        made eleven boundary tests fail, correctly. The id is still generated, still on
        every log record for the request, and still the way an operator joins a customer's
        report to the logs; it is simply not handed to the customer.
        """
        token = set_correlation_id(accept_correlation_id(request.headers.get(CORRELATION_HEADER)))
        started = time.perf_counter()

        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_request_bytes:
            # Refused before the body is read, so an oversized request never occupies
            # memory proportional to its size.
            log_event(
                logger,
                logging.WARNING,
                "request_body_too_large",
                method=request.method,
                request_bytes=int(declared),
                status_code=413,
            )
            response = JSONResponse(
                status_code=413,
                content={
                    "code": "request_too_large",
                    "message": "The request body is larger than this endpoint accepts.",
                    "field": None,
                    "detail": None,
                },
            )
            _attach_correlation(request, response)
            reset_correlation_id(token)
            return response

        try:
            response = await call_next(request)
        except Exception:
            # Logged as a type name by the logging filter, never as a rendered
            # exception. Re-raised so the framework still returns its 500.
            log_event(
                logger,
                logging.ERROR,
                "request_failed",
                method=request.method,
                route=_route_template(request),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            reset_correlation_id(token)
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        _attach_correlation(request, response)
        log_event(
            logger,
            logging.INFO,
            "http_request",
            method=request.method,
            route=_route_template(request),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        reset_correlation_id(token)
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        # Staff API responses are never cached by shared caches.
        response.headers.setdefault("Cache-Control", "no-store")
        if not request.url.path.startswith((PUBLIC_PREFIX, ACCOUNT_PREFIX)):
            # The staff surface only. `Pragma: no-cache` is the HTTP/1.0 spelling of the
            # same instruction, for the proxies and browser heuristics that still read it
            # (UAT-AD-01: after sign-out, Back must not show customer names). The public
            # and Customer Account surfaces keep their own, separately asserted header
            # sets; adding a header there would be a contract change for no gain.
            response.headers.setdefault("Pragma", "no-cache")
        if request.url.path.startswith(PUBLIC_PREFIX):
            # The public surface sets its own headers in the route handler; this repeats
            # them here so a failure raised before the handler runs -- a rate-limit
            # rejection, a request-validation error, an unhandled exception -- still
            # carries them. Headers a customer's browser relies on for privacy should not
            # depend on which code path produced the response.
            for header, value in PUBLIC_HEADERS.items():
                response.headers[header] = value
        elif request.url.path.startswith(ACCOUNT_PRIVATE_PREFIXES):
            # The same repetition, for the same reason, on the authenticated customer
            # surface -- and it is not redundant. Phase 11's shipment routes set these in
            # the handler, and a 404, a 403 or a 429 is raised *before* the handler returns,
            # so the route's copy never reaches those responses. Without this branch an
            # authenticated shipment result carried `no-store` while the refusal that
            # followed it carried a different value, which is both a weaker privacy
            # guarantee on the failure path and a difference between two responses that
            # are supposed to be indistinguishable.
            #
            # Scoped to the shipment prefix rather than the whole account surface on
            # purpose: the Phase 9 routes already answer with the application-wide
            # `Cache-Control: no-store` and their responses are asserted byte for byte by
            # `test_account_sessions.py`. Widening their headers would be a Phase 9
            # contract change Phase 11 has no reason to make.
            for header, value in ACCOUNT_HEADERS.items():
                response.headers[header] = value
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        headers = {}
        if isinstance(exc, RateLimitedError):
            headers["Retry-After"] = str(exc.retry_after)

        if request.url.path.startswith(PUBLIC_PREFIX):
            # The public failure body is deliberately narrower than the staff one: two
            # keys, no field, no detail. `detail` on a staff error carries context such as
            # which permission was missing or how many seconds remain, and none of that
            # belongs on a customer-facing response -- a retry-after value in the body as
            # well as the header would be one more thing that differs between two failures
            # that must be indistinguishable.
            code = "tracking_not_found" if exc.status_code == 404 else exc.code
            return JSONResponse(
                status_code=exc.status_code,
                content={"code": code, "message": exc.message},
                headers=headers,
            )

        if request.url.path.startswith(ACCOUNT_PREFIX):
            # Three keys, always the same three. `detail` is dropped for the public reason
            # -- a retry-after count in the body as well as the header is one more value
            # that differs between two failures -- but `field` is **kept**, because
            # `STATE_MACHINES.md` section 2 requires field-level validation errors for
            # *format* and forbids them for *existence*. A registration form whose errors
            # named no field would be a form nobody could fill in.
            #
            # `field` never varies by account: it is set only by a format check, which
            # performs no lookup, and by the single-answer token failure, where it is the
            # constant "token". It is present and null on every other failure, so the shape
            # itself is fixed (instruction section 13).
            return JSONResponse(
                status_code=exc.status_code,
                content={"code": exc.code, "message": exc.message, "field": exc.field},
                headers=headers,
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "field": exc.field,
                "detail": exc.detail,
            },
            headers=headers,
        )

    # --- Health ----------------------------------------------------------------------
    #
    # Three endpoints, all unauthenticated, and none of them says anything an anonymous
    # caller should not hear. **No path, no revision, no version, no hostname, no
    # environment name, no configuration value, no stack trace, no row count, no customer
    # value, and no tracking reference appears in any of these responses.**
    #
    # The environment name used to be in `/health`. It was removed in Phase 5B: it is a
    # deployment internal, it told an anonymous caller whether they had found production
    # or staging, and nothing consumed it.
    #
    # Readiness reports each check by name with a coarse `ok` / `failed`. That is enough
    # for an operator to know which runbook to open and not enough to learn anything
    # about the installation.

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        """Liveness. The process is up and can answer. Kept at its original path."""
        return {"status": "ok"}

    @app.get("/health/live", tags=["meta"])
    def liveness() -> dict:
        """Liveness. Answering at all is the whole check -- restart me if this fails."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["meta"])
    def readiness(response: Response) -> dict:
        """Readiness. Can this process serve a request that touches the database?

        Distinct from liveness on purpose. A process whose database volume has not
        mounted is alive and should not receive traffic; restarting it will not help, and
        a load balancer that cannot tell the difference will restart it forever.
        """
        checks = {
            "database": "ok" if _check_database_reachable() else "failed",
            "migrations": "ok" if _check_migrations_current() else "failed",
            "timezone": "ok" if is_known_timezone(settings.default_timezone) else "failed",
        }
        ready = all(state == "ok" for state in checks.values())
        if not ready:
            response.status_code = 503
            log_event(
                logger,
                logging.ERROR,
                "readiness_failed",
                check=",".join(sorted(name for name, s in checks.items() if s == "failed")),
            )
        return {"status": "ready" if ready else "not_ready", "checks": checks}

    # The public router is mounted first so its concrete `/public/track/{reference}` path
    # is unambiguous, and so the separation reads top-down in one place.
    app.include_router(public_router, prefix=PUBLIC_PREFIX)
    # Mounted before the staff router for the same reason the public one is: its concrete
    # paths stay unambiguous, and the three surfaces read top-down in one place.
    app.include_router(account_router, prefix=ACCOUNT_PREFIX)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    # The end-to-end handshake, and nothing else, is mounted here -- and only when the
    # process is running as the browser suite's own backend. Not hidden behind a flag
    # checked inside the handler: the router is never included, so in development,
    # production, UAT and pytest the path does not exist, does not appear in the route
    # table, and cannot appear in the OpenAPI document. See `app.api.e2e`.
    if e2e_guard.is_e2e_environment(settings.environment):
        app.include_router(e2e_router, prefix=E2E_PREFIX, include_in_schema=False)
    return app


app = create_app()
