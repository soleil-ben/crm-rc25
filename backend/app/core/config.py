"""Application configuration.

All secrets and environment-specific values come from environment variables or a
local ``.env`` file. ``.env`` is never committed; ``.env.example`` holds placeholders
only (CRM.md section 3).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Environment -----------------------------------------------------
    environment: str = Field(default="development")
    app_name: str = "Solaris Express CRM"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False

    # --- Logging (Phase 5B) ----------------------------------------------
    #: Root log level. `DEBUG` is refused in production: the redaction filter holds, but
    #: debug records are written by libraries that were never asked to think about
    #: privacy, and the volume alone makes a log shipper the largest copy of the data.
    log_level: str = "INFO"
    #: One JSON object per line. False gives the human-readable development format.
    log_json: bool = True

    #: Largest request body the application will accept, in bytes. A separate, far
    #: smaller bound applies to the CSV import (`csv_safety.MAX_FILE_BYTES`, 2 MiB); this
    #: is the outer limit that stops an unbounded body from being buffered at all.
    max_request_bytes: int = 8 * 1024 * 1024

    # --- Database --------------------------------------------------------
    # The SQLite file lives outside the source tree by default (CRM.md section 3).
    database_url: str = Field(
        default=f"sqlite:///{(REPO_ROOT / 'data' / 'solaris_crm.db').as_posix()}"
    )
    sqlite_busy_timeout_ms: int = 5000

    # --- Security --------------------------------------------------------
    secret_key: str = Field(default="dev-only-insecure-secret-change-me")
    session_cookie_name: str = "solaris_session"
    csrf_cookie_name: str = "solaris_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    session_idle_minutes: int = 480
    session_absolute_hours: int = 24
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    cookie_domain: str | None = None

    # --- CORS ------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Rate limits -----------------------------------------------------
    login_rate_limit_attempts: int = 8
    login_rate_limit_window_seconds: int = 300
    public_tracking_rate_limit_attempts: int = 30
    public_tracking_rate_limit_window_seconds: int = 60

    # Whether a forwarding header may be believed. **Default false**, and it must stay
    # false until a specific reverse proxy is deployed *and* the ASGI server is told to
    # trust only that proxy's address (DEC-0007, DEC-0048).
    #
    # This is not merely advisory. Uvicorn enables `--proxy-headers` by default and
    # trusts `127.0.0.1`, which means it rewrites the peer address from
    # `X-Forwarded-For` before the application ever sees it. An application that assumed
    # "we do not read that header, so we are safe" would be wrong, and the rate limit
    # would be bypassable by anyone who could reach the server on loopback. When this
    # setting is false the public limiter folds every request carrying a forwarding
    # header into one shared bucket, so a spoofer cannot mint a fresh allowance per
    # request no matter what the server did to the scope.
    trust_proxy_headers: bool = False

    #: The other half of DEC-0048, made enforceable in Phase 5B. Addresses of the
    #: reverse proxies whose forwarding headers may be believed, comma-separated.
    #:
    #: `trust_proxy_headers` alone is not a configuration, it is half of one. Trusting
    #: the header without also telling the ASGI server which peer may set it means any
    #: caller who can reach the socket can choose their own rate-limit bucket. Production
    #: therefore refuses to start with one half set and the other empty -- both, or
    #: neither. **Both are empty and false today, and Phase 5B did not change that.**
    trusted_proxy_hosts: str = ""

    # --- Business defaults ----------------------------------------------
    default_timezone: str = "America/Toronto"
    default_currency: str = "CAD"
    tracking_base_url: str = "http://localhost:5173/track"

    # --- Public tracking page --------------------------------------------
    # Shown as "Contact Solaris Express" on the public tracking page. Empty means the
    # link is omitted rather than pointing somewhere invented.
    public_help_url: str = ""
    # Hosts a stored carrier link may use before the public page will render it. A link
    # is *displayed* only; it is never fetched server-side (CRM.md section 9). An empty
    # list means no carrier link is ever shown publicly.
    public_carrier_link_hosts: str = (
        "www.ups.com,www.fedex.com,www.purolator.com,www.canadapost-postescanada.ca,"
        "www.dhl.com,tools.usps.com,www.usps.com,vnpost.vn,viettelpost.com.vn"
    )

    # --- Demo / seed guardrails -----------------------------------------
    allow_demo_seed: bool = True

    # --- Phase 4A: provider integration infrastructure --------------------
    #
    # None of these configures a provider. No provider account exists, the adapter
    # registry is empty, and no request has ever been made to a carrier or to ShipStation
    # by this application (docs/INTEGRATIONS.md). These are the bounds the durable inbox
    # and the worker operate under, so they are correct before a provider is chosen.
    #
    # A missing API key must never stop the CRM from starting (CRM.md section 3), so
    # nothing here is required and nothing here raises when it is absent.

    #: Largest webhook body that will be accepted. A larger delivery is refused on
    #: arrival and stored as a digest without its body, rather than truncated: a
    #: truncated payload parses into something that is not what the provider sent.
    integration_webhook_max_bytes: int = 256 * 1024
    #: Content types a webhook delivery may declare. Anything else is rejected rather
    #: than parsed hopefully.
    integration_webhook_content_types: str = "application/json"

    #: How long a worker may hold a claimed job before the lease expires and another
    #: worker may reclaim it. Long enough that a slow provider read does not lose its
    #: lease mid-flight; short enough that a crashed worker is recovered promptly.
    integration_job_lease_seconds: int = 300
    #: Attempts before a retryable job stops and goes to the failed-job review queue.
    integration_job_max_attempts: int = 5
    #: Attempts before an *authentication* failure stops. Deliberately far lower:
    #: repeating a rejected credential achieves nothing and can lock an account.
    integration_auth_max_attempts: int = 2
    #: First backoff step, doubled per attempt, with full jitter.
    integration_retry_base_seconds: int = 30
    #: Backoff ceiling, and also the ceiling applied to a provider Retry-After, so a
    #: provider cannot park a job for an arbitrary length of time.
    integration_retry_max_seconds: int = 3600
    #: Jobs claimed per worker pass.
    integration_worker_batch_size: int = 20
    #: Seconds a continuous worker sleeps when it finds nothing to do.
    integration_worker_poll_seconds: int = 15

    #: Hosts a provider resource URL may be fetched from. **Empty, and it stays empty**
    #: until official documentation and the real account confirm which hosts and paths a
    #: fetch would need. Empty means nothing is ever fetched, which is the correct
    #: behaviour for a provider nobody has verified (CRM.md section 9).
    integration_resource_allowed_hosts: str = ""
    #: Path prefixes on those hosts. Also empty, for the same reason.
    integration_resource_allowed_path_prefixes: str = ""

    # --- Vendor tariffs and exchange rates (Phase 13A) ---------------------------------
    #: Largest tariff workbook the import route accepts, in bytes. The vendor's 12 Oct 2026
    #: file is 0.95 MB; openpyxl's re-save of it is 1.4 MB.
    tariff_import_max_bytes: int = 4 * 1024 * 1024
    #: How often the exchange-rate worker asks the bank, in continuous mode. The bank
    #: publishes a handful of updates a day; five minutes is the handoff's figure (§6).
    fx_poll_seconds: int = 300
    #: A verified snapshot older than this is reported ``stale`` and the pricing engine
    #: must say so rather than price silently. One day: the bank publishes every business
    #: day and a weekend gap is expected, not an outage.
    fx_stale_after_minutes: int = 24 * 60

    # --- Vendor rate-email intake (Phase 13H, OD-76) ------------------------------------
    #: Largest ``.eml`` the intake accepts (upload or folder), in bytes. The attachment
    #: itself is still held to ``tariff_import_max_bytes``.
    tariff_intake_max_eml_bytes: int = 15 * 1024 * 1024
    #: The folder the intake worker reads ``*.eml`` from (stand-in for a live mailbox: no
    #: mailbox connection exists). Empty: ``data/tariff_intake`` under the repository,
    #: which is git-ignored. Processed files move to ``processed/`` or ``failed/`` beneath
    #: it; a held sender's workbook waits in ``held/``. Nothing is deleted.
    tariff_intake_dir: str = ""

    # --- Phase 9: Customer Account ---------------------------------------
    #
    # The authenticated customer surface. **Nothing here is shared with the staff realm**,
    # and that starts with the names: a cookie called `solaris_session` presented to a
    # Customer Account route must resolve nothing, and it cannot, because the resolver
    # reads a different table and the cookie it reads has a different name (DEC-0090).
    #
    # Registration **cannot launch in production** while OD-34 (no email provider) and
    # OD-37 (no approved terms text) are unsatisfied. That is enforced, not documented:
    # `account_delivery_blockers` below returns the reasons, the routes refuse while it is
    # non-empty, and no default quietly satisfies either.

    account_session_cookie_name: str = "solaris_account_session"
    account_csrf_cookie_name: str = "solaris_account_csrf"
    account_csrf_header_name: str = "X-Account-CSRF-Token"
    #: Shorter than the staff 480. A customer session is often on a shared or mobile
    #: device and is used briefly (`SESSION_COOKIES_AND_CSRF.md` section 4).
    account_session_idle_minutes: int = 60
    account_session_absolute_hours: int = 24

    #: Hours, not days (OD-36). Short enough that a forwarded message stops working, long
    #: enough that somebody who reads their mail in the evening is not locked out.
    account_verification_token_hours: int = 24
    #: One hour since the 2026-10-14 fix pack (DEC-0121). A reset link is requested by the
    #: person about to use it, so an hour costs a legitimate user nothing, and it halves the
    #: window in which a copy left in the browser's history database (DEC-0119) still works.
    account_password_reset_token_hours: int = 1

    #: Minimum customer password length. Length only: composition rules push people toward
    #: `Password1!` (`RATE_LIMITS_AND_ABUSE.md` section 5).
    account_min_password_length: int = 12

    # Rate-limit buckets, all in the `account:` namespace so a customer-side flood can
    # never consume the staff login or public tracking allowance.
    account_register_ip_attempts: int = 5
    account_register_ip_window_seconds: int = 3600
    account_register_address_attempts: int = 2
    account_register_address_window_seconds: int = 86400
    account_resend_ip_attempts: int = 5
    account_resend_ip_window_seconds: int = 3600
    account_resend_address_attempts: int = 3
    account_resend_address_window_seconds: int = 3600
    account_signin_ip_attempts: int = 10
    account_signin_ip_window_seconds: int = 300
    account_signin_address_attempts: int = 6
    account_signin_address_window_seconds: int = 900
    account_reset_ip_attempts: int = 5
    account_reset_ip_window_seconds: int = 3600
    account_reset_address_attempts: int = 3
    account_reset_address_window_seconds: int = 3600
    account_token_ip_attempts: int = 20
    account_token_ip_window_seconds: int = 600
    account_token_identity_attempts: int = 10
    account_token_identity_window_seconds: int = 3600

    # Authenticated shipment reads (`RATE_LIMITS_AND_ABUSE.md` §3, `account:read:<identity>`).
    # 300 in 5 minutes: fifteen full pages a minute sustained, which no person paging through
    # their own history reaches and which bounds what a stolen session can scrape.
    account_read_identity_attempts: int = 300
    account_read_identity_window_seconds: int = 300

    #: Failed sign-ins inside the window before `locked_until` is set. Bounded in time and
    #: never permanent: a permanent lockout hands an attacker a way to disable any customer
    #: they can name.
    account_lockout_threshold: int = 10
    account_lockout_window_minutes: int = 15
    account_lockout_minutes: int = 15

    #: Largest Customer Account request body. Far below `max_request_bytes`, because none
    #: of these endpoints accepts a file and a registration form is a few hundred bytes.
    account_max_body_bytes: int = 16 * 1024

    #: Which `EmailTransport` to build. `null` records that a send was requested and
    #: produces nothing; `capture` writes to the local capture directory and opens no
    #: socket; `production` **is not implemented** and selecting it fails at startup,
    #: because OD-34 has selected no provider. There is deliberately no value that means
    #: "try production, fall back to capture".
    account_email_transport: str = "null"
    #: Where the capture transport writes. Under the git-ignored development data
    #: directory; never committed, never served, never reachable over HTTP.
    account_email_capture_dir: str = ""
    #: Development and UAT: behave as production does while no email provider is selected
    #: (OD-34), so the closed-registration screen can be tested without a production
    #: configuration (`CA-REG-09`). It can only *add* the production delivery blocker --
    #: registration, resend and reset refuse, sign-in still works -- and never removes one.
    account_rehearse_no_email_provider: bool = False

    #: The terms and privacy versions presented at registration. Both are **placeholders
    #: that name themselves as placeholders**, and production registration refuses while
    #: either still is one (OD-37). Supplying a real version string is an owner action that
    #: follows approved legal text, not a configuration convenience.
    account_terms_version: str = "PLACEHOLDER-terms-unapproved"
    account_privacy_version: str = "PLACEHOLDER-privacy-unapproved"

    #: English only for release 1 (OD-39). Vietnamese customer-account wording is disabled
    #: until a qualified reviewer approves all four categories.
    # OD-71 (2026-10-20): Vietnamese first, English as an option.
    account_supported_languages: str = "vi,en"

    @field_validator("cookie_samesite")
    @classmethod
    def _validate_samesite(cls, value: str) -> str:
        allowed = {"lax", "strict", "none"}
        if value.lower() not in allowed:
            raise ValueError(f"cookie_samesite must be one of {sorted(allowed)}")
        return value.lower()

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def public_carrier_link_host_list(self) -> list[str]:
        return [
            host.strip().lower()
            for host in self.public_carrier_link_hosts.split(",")
            if host.strip()
        ]

    @property
    def integration_webhook_content_type_list(self) -> list[str]:
        return [
            value.strip().lower()
            for value in self.integration_webhook_content_types.split(",")
            if value.strip()
        ]

    @property
    def integration_resource_host_list(self) -> list[str]:
        """Hosts a provider resource URL may use. Empty today, and correctly so."""
        return [
            host.strip().lower()
            for host in self.integration_resource_allowed_hosts.split(",")
            if host.strip()
        ]

    @property
    def integration_resource_path_prefix_list(self) -> list[str]:
        return [
            prefix.strip()
            for prefix in self.integration_resource_allowed_path_prefixes.split(",")
            if prefix.strip()
        ]

    @property
    def account_supported_language_list(self) -> list[str]:
        return [
            value.strip().lower()
            for value in self.account_supported_languages.split(",")
            if value.strip()
        ]

    @property
    def account_email_capture_path(self) -> Path:
        """Where captured mail lands. Under the git-ignored development data directory.

        Defaults beside the SQLite file rather than inside the source tree, for the same
        reason the database does: a captured verification link is a live credential for
        somebody's account, and a deployment that replaces the source must not be able to
        publish one.
        """
        configured = self.account_email_capture_dir.strip()
        if configured:
            return Path(configured)
        return REPO_ROOT / "data" / "account_mail"

    @property
    def tariff_intake_path(self) -> Path:
        """The rate-email intake folder (Phase 13H). Under the git-ignored data directory."""
        configured = self.tariff_intake_dir.strip()
        if configured:
            return Path(configured)
        return REPO_ROOT / "data" / "tariff_intake"

    @property
    def sqlite_path(self) -> Path | None:
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            raw = self.database_url[len(prefix) :]
            if raw and raw != ":memory:":
                return Path(raw)
        return None

    @property
    def trusted_proxy_host_list(self) -> list[str]:
        """Proxies whose forwarding headers may be believed. Empty today (DEC-0048)."""
        return [host.strip() for host in self.trusted_proxy_hosts.split(",") if host.strip()]


# --- Customer Account email transport and launch gates (OD-34, OD-37) ---------
#
# Three transport names, and the set is closed. There is no value meaning "production if
# configured, capture otherwise": a silent fallback would mean a production deployment
# quietly writing verification links to a directory instead of sending them, and nobody
# finding out until a customer said they never got the email (DEC-0094).

#: Records that a send was requested and produces nothing. The default, and the default in
#: tests, so a test that wants to read a message opts into the capture explicitly.
TRANSPORT_NULL = "null"
#: Writes the message to a local directory. Opens no socket. Development and UAT only.
TRANSPORT_CAPTURE = "capture"
#: **Not implemented.** Named so that selecting it fails loudly rather than being an
#: unrecognized string that falls through to something safe-looking.
TRANSPORT_PRODUCTION = "production"

EMAIL_TRANSPORT_NAMES = (TRANSPORT_NULL, TRANSPORT_CAPTURE, TRANSPORT_PRODUCTION)

#: Prefix marking a terms or privacy version as not yet approved (OD-37). A version string
#: that starts with this is a placeholder whatever else it says.
UNAPPROVED_VERSION_PREFIX = "PLACEHOLDER-"


def email_transport_problems(settings: Settings) -> list[str]:
    """Reasons this transport selection must not start at all, in any environment.

    Separate from `production_configuration_problems` because two of these are wrong
    everywhere, not only in production: an unrecognized transport name is a typo that would
    otherwise be resolved by a fallback nobody wrote down, and `production` is a transport
    with nothing behind it.
    """
    problems: list[str] = []
    selected = settings.account_email_transport.strip().lower()

    if selected not in EMAIL_TRANSPORT_NAMES:
        problems.append(
            f"ACCOUNT_EMAIL_TRANSPORT={settings.account_email_transport!r} is not one of "
            f"{list(EMAIL_TRANSPORT_NAMES)}. There is no fallback: an unrecognized value is "
            "a typo, and guessing what it meant is how mail stops being sent quietly"
        )
        return problems

    if selected == TRANSPORT_PRODUCTION:
        problems.append(
            "ACCOUNT_EMAIL_TRANSPORT=production selects a transport that is not "
            "implemented. OD-34 has selected no email provider, and production launch of "
            "customer registration is blocked until the owner selects one using verified "
            "documentation with data residency confirmed. Writing an adapter now would be "
            "choosing a provider by implementation"
        )

    if settings.is_production and selected == TRANSPORT_CAPTURE:
        problems.append(
            "ACCOUNT_EMAIL_TRANSPORT=capture must not be used in production. The capture "
            "transport writes verification and password-reset links to a local directory "
            "and sends nothing, so registration would appear to work while no customer "
            "ever received a message"
        )

    return problems


def account_delivery_blockers(settings: Settings) -> list[str]:
    """Why Customer Account mail cannot be delivered in this configuration. Codes, not prose.

    Returned as reason **codes** because they are logged into the structured `reason_code`
    field, which is constrained to a vocabulary token so that nothing free-form can be
    smuggled through it.

    An empty list means mail can genuinely be delivered. In production today the list is
    never empty, which is the point: registration, resend and password-reset refuse at the
    route while it is non-empty (OD-34), and the rest of the application still starts,
    because blocking the Staff Portal and Public Tracking over a surface that has not
    launched would be the wrong trade.
    """
    blockers: list[str] = []
    if not settings.is_production:
        # The rehearsal reproduces the production gate exactly -- the same code, so the
        # same refusal at the same routes -- rather than approximating it (CA-REG-09).
        if settings.account_rehearse_no_email_provider:
            blockers.append("email_provider_not_selected")
        return blockers
    if settings.account_email_transport.strip().lower() != TRANSPORT_PRODUCTION:
        blockers.append("email_provider_not_selected")
    return blockers


def account_registration_blockers(settings: Settings) -> list[str]:
    """Why registration in particular cannot run. Delivery blockers plus the legal gate.

    OD-37 requires a versioned, timestamped terms and privacy acknowledgement, and blocks
    production registration until approved legal text and version identifiers are supplied.
    A placeholder version recorded against a real customer would be an acknowledgement of
    nothing, which is worse than refusing.
    """
    blockers = account_delivery_blockers(settings)
    if not settings.is_production:
        return blockers
    for value in (settings.account_terms_version, settings.account_privacy_version):
        if value.strip().startswith(UNAPPROVED_VERSION_PREFIX):
            blockers.append("terms_version_not_approved")
            break
    return blockers


#: The development secret. Named rather than repeated so a test can assert on the same
#: constant the refusal uses.
DEV_SECRET_KEY = "dev-only-insecure-secret-change-me"

#: Shortest production secret. 32 characters of a generated value; the check exists
#: because "set it explicitly" is satisfied by typing `changeme`.
MIN_SECRET_KEY_LENGTH = 32

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]")


def _is_local_origin(value: str) -> bool:
    lowered = value.lower()
    return any(host in lowered for host in _LOCAL_HOSTS)


def production_configuration_problems(settings: Settings) -> list[str]:
    """Every reason this configuration must not run in production.

    Returned as a list rather than raised one at a time so an operator fixes the whole
    configuration in one pass instead of discovering the next problem on the next
    restart. Each entry names the variable and what is wrong with it.

    The rule these follow: **refuse what is unsafe, warn about what is merely
    incomplete.** An empty `PUBLIC_HELP_URL` produces a page with no contact link, which
    is a business problem and a documented gate -- not a reason to refuse to serve
    tracking. A development `SECRET_KEY` in production is a reason.
    """
    problems: list[str] = []

    if settings.secret_key == DEV_SECRET_KEY:
        problems.append("SECRET_KEY is still the development default; generate one")
    elif len(settings.secret_key) < MIN_SECRET_KEY_LENGTH:
        problems.append(
            f"SECRET_KEY is shorter than {MIN_SECRET_KEY_LENGTH} characters; "
            "generate a random value rather than typing one"
        )

    if not settings.cookie_secure:
        problems.append("COOKIE_SECURE must be true in production")

    if settings.cookie_samesite == "none" and not settings.cookie_secure:
        problems.append("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")

    if settings.allow_demo_seed:
        problems.append("ALLOW_DEMO_SEED must be false in production")

    if settings.debug:
        problems.append("DEBUG must be false in production")

    if settings.log_level.upper() == "DEBUG":
        problems.append(
            "LOG_LEVEL=DEBUG must not be used in production; library debug records are "
            "written by code that was never asked to think about privacy"
        )

    origins = settings.cors_origin_list
    if not origins:
        problems.append("CORS_ORIGINS must name the production origin explicitly")
    else:
        for origin in origins:
            if _is_local_origin(origin):
                problems.append(f"CORS_ORIGINS contains a development host: {origin}")
            elif not origin.startswith("https://"):
                problems.append(f"CORS_ORIGINS entry is not https: {origin}")

    tracking = settings.tracking_base_url.strip()
    if not tracking:
        problems.append("TRACKING_BASE_URL must be set; it is printed on every label")
    elif _is_local_origin(tracking):
        problems.append(
            "TRACKING_BASE_URL points at a development host; labels printed with it "
            "carry a QR code that resolves nowhere for a customer"
        )
    elif not tracking.startswith("https://"):
        problems.append("TRACKING_BASE_URL must be https")

    # DEC-0048: both halves, or neither. One half alone is worse than neither, because
    # it looks configured while leaving the rate limiter keyed on a caller-chosen value.
    if settings.trust_proxy_headers and not settings.trusted_proxy_host_list:
        problems.append(
            "TRUST_PROXY_HEADERS is true but TRUSTED_PROXY_HOSTS is empty. Both, or "
            "neither (DEC-0048): trusting the header without naming the proxy lets any "
            "caller who can reach the socket choose their own rate-limit bucket"
        )
    if settings.trusted_proxy_host_list and not settings.trust_proxy_headers:
        problems.append(
            "TRUSTED_PROXY_HOSTS is set but TRUST_PROXY_HEADERS is false; the proxy "
            "configuration is half-applied (DEC-0048)"
        )

    problems.extend(database_path_problems(settings))
    return problems


def database_path_problems(settings: Settings) -> list[str]:
    """Reasons the configured database location is unsafe for production.

    Checked separately from the rest because it is the one setting whose mistake is not
    recoverable by editing an environment variable: a database written inside the source
    tree is deleted by the next clean checkout, and one written to a relative path
    follows the working directory of whatever started the process.
    """
    problems: list[str] = []
    path = settings.sqlite_path
    if path is None:
        return problems

    if not path.is_absolute():
        problems.append(
            f"DATABASE_URL must be an absolute path in production; got {path.as_posix()!r}. "
            "A relative path follows the process working directory"
        )
        return problems

    resolved = path.resolve()
    source_tree = (BACKEND_ROOT / "app").resolve()
    if resolved == source_tree or source_tree in resolved.parents:
        problems.append(
            "DATABASE_URL points inside the application source tree; a deployment that "
            "replaces the source replaces the database"
        )

    # The other direction of the Phase 10 E2E guard. `app.core.e2e_guard` stops an E2E
    # backend serving a real database; this stops a real deployment serving a scratch one.
    # The suffix is the whole signal -- a file named `.e2e.db` is created, seeded with
    # synthetic data and deleted by a browser run, and production pointed at one would be
    # emptied by the next suite. Spelled literally rather than imported because
    # `e2e_guard` imports this module.
    if resolved.name.lower().endswith(".e2e.db"):
        problems.append(
            "DATABASE_URL names an end-to-end scratch database (.e2e.db). Those are "
            "created, seeded and deleted by the browser suite; production must never "
            "point at one"
        )

    parent = resolved.parent
    if not parent.exists():
        problems.append(
            f"The database directory does not exist: {parent.as_posix()}. Create it, on "
            "persistent storage, before starting"
        )
    return problems


#: Startup warning codes, and what each one means. Short slugs rather than sentences
#: because they are logged into a structured `reason_code` field that an operator alerts
#: on, and because that field is constrained to a vocabulary token -- a rule that exists
#: so a customer's name cannot be smuggled into a field nobody thought to check.
#: `docs/DEPLOYMENT.md` carries the full explanation of each.
CONFIGURATION_WARNING_CODES = {
    "public_help_url_empty": (
        "PUBLIC_HELP_URL is empty; the public tracking page shows no contact link, "
        "including on an exception callout that tells the customer to get in touch."
    ),
    "public_carrier_link_hosts_empty": (
        "PUBLIC_CARRIER_LINK_HOSTS is empty; no carrier link will ever be shown."
    ),
    "tracking_base_url_is_development": (
        "TRACKING_BASE_URL points at a development host; any label printed now carries "
        "a QR code that resolves nowhere for a customer."
    ),
}


def configuration_warnings(settings: Settings) -> list[str]:
    """Incomplete rather than unsafe. Logged at startup; never fatal.

    These are the settings whose absence produces a worse product but not an insecure
    one, and each is already an open gate in `docs/OPERATIONS.md`. Refusing to start over
    them would mean the application could not run until business decisions nobody has
    made yet were made.

    Returns codes, not sentences. `CONFIGURATION_WARNING_CODES` maps each to its
    explanation.
    """
    warnings: list[str] = []
    if not settings.public_help_url.strip():
        warnings.append("public_help_url_empty")
    if not settings.public_carrier_link_host_list:
        warnings.append("public_carrier_link_hosts_empty")
    if not settings.is_production and _is_local_origin(settings.tracking_base_url):
        warnings.append("tracking_base_url_is_development")
    return warnings


@lru_cache
def get_settings() -> Settings:
    from app.core import e2e_guard

    settings = Settings()

    # Checked in every environment, not only production: an unrecognized transport name is
    # a typo, and `production` names a transport nobody has written. Neither has a safe
    # interpretation, so neither gets one.
    transport_problems = email_transport_problems(settings)
    if transport_problems:
        listed = "\n".join(f"  - {problem}" for problem in transport_problems)
        raise RuntimeError(
            f"Refusing to start: {len(transport_problems)} unusable email transport "
            f"setting(s).\n{listed}"
        )

    if settings.is_production:
        # Fail fast rather than run production with development defaults. Every problem
        # at once, so the operator fixes the configuration in one pass.
        problems = production_configuration_problems(settings)
        if problems:
            listed = "\n".join(f"  - {problem}" for problem in problems)
            raise RuntimeError(
                f"Refusing to start: {len(problems)} unsafe production setting(s).\n{listed}"
            )

    # The E2E environment is the browser suite's, and only the browser suite's. A backend
    # running under it refuses anything but an approved scratch database, and refuses to
    # run at all without the identifier of the run that started it -- so a process that
    # somehow inherited `ENVIRONMENT=e2e` by accident stops here rather than serving.
    #
    # Imported inside the function because `e2e_guard` imports this module for the two
    # repository roots; at module scope the pair would be circular.
    if e2e_guard.is_e2e_environment(settings.environment):
        e2e_problems = e2e_guard.e2e_startup_problems(
            settings.database_url, e2e_guard.current_run_id()
        )
        if e2e_problems:
            listed = "\n".join(f"  - {problem}" for problem in e2e_problems)
            raise RuntimeError(
                f"Refusing to start: {len(e2e_problems)} unsafe end-to-end setting(s).\n{listed}"
            )
    return settings


settings = get_settings()
