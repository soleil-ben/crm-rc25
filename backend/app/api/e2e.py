"""The handshake that proves a browser suite is talking to its own backend (DEC-0112).

Mounted **only** when ``ENVIRONMENT`` is ``e2e``. ``app.main.create_app`` asks
``e2e_guard.is_e2e_environment`` before including this router, so in development,
production, UAT and pytest the path does not exist, is not routed, and is not in the
OpenAPI document -- not because it is hidden, but because it was never added.

Why it exists
-------------
``scripts/e2e_env.py`` refuses to build or serve anything but an approved ``.e2e.db``
scratch database. That check runs inside the launcher, and the launcher is not what
Playwright connects to: the browser opens a URL, and whatever is listening on that port
answers. On 2026-09-20 what answered was a development backend somebody had already
started, and the staff specs wrote forty customers, thirty-two import batches and a
hundred and ninety-five audit rows into ``data/solaris_crm.db``.

So the run proves the connection instead of assuming it. Each run mints a random
identifier and gives it to two places and no others: the environment of the backend it
starts, and a marker row inside the scratch database that backend was told to serve. This
endpoint compares a caller's identifier against both. Agreement means the process, the
database and the suite all belong to the same run. Anything else -- a stale backend from
yesterday's run, a development server that never heard of the endpoint, the right process
pointed at the wrong file -- fails to agree, and ``globalSetup.js`` stops the suite before
a single test can authenticate.

What it will not say
--------------------
The response is a status and nothing else. No path, no database name, no revision, no row
count, no environment value, no configuration, and never the expected identifier: a caller
who does not already know it learns nothing by asking. The comparison is one-way for that
reason, and it is why a mismatch and an absent marker answer with the same shape.

The identifier is not a credential. It authorises no request, unlocks no data, and carries
no session. Presenting the right one gets ``{"status": "ok"}`` and no access to anything;
presenting the wrong one gets a 409 and no access to anything. It answers "are you the
process this run created?" and that is the whole of its authority.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, Response
from sqlalchemy import text

from app.core import db as db_module
from app.core import e2e_guard

router = APIRouter(tags=["e2e"], include_in_schema=False)

#: The header the suite presents its identifier in. A header rather than a query parameter
#: so it stays out of access logs that record paths, and out of a browser's history.
RUN_ID_HEADER = "X-E2E-Run-Id"


def _database_run_id() -> str | None:
    """The marker the launcher wrote into the database this process is actually serving.

    Read through the application's own engine, so it is the database the request handlers
    would write to and not a second opinion about what the configuration says. Reached
    through the module rather than bound at import, so a test can point it somewhere else
    -- ``app.core.db.engine`` is built from ``DATABASE_URL``, which under pytest is the
    development database, and a test that exercised this must not open that file.
    """
    try:
        with db_module.engine.connect() as connection:
            row = connection.execute(
                text(f"SELECT run_id FROM {e2e_guard.RUN_MARKER_TABLE} LIMIT 1")  # noqa: S608
            ).fetchone()
    except Exception:
        # A missing table is the ordinary answer here: it means this process is serving a
        # database no E2E run created. Deliberately not logged with the exception -- a
        # driver's message carries the connection string, which carries the path.
        return None
    return row[0] if row and isinstance(row[0], str) else None


@router.get("/handshake")
def handshake(
    response: Response,
    x_e2e_run_id: str | None = Header(default=None, alias=RUN_ID_HEADER),
) -> dict:
    """Confirm that this process and its database both belong to the caller's run.

    409 rather than 403 on disagreement: nothing was refused for lack of permission. The
    caller reached a backend that belongs to a different run, which is a conflict about
    identity, and the suite's response to it is to stop rather than to retry with
    something better.
    """
    expected = e2e_guard.current_run_id()
    presented = (x_e2e_run_id or "").strip()

    # `compare_digest` not because the identifier is secret -- it is not -- but because
    # the alternative is an early-exit comparison, and a timing-visible one would be a
    # small standing invitation to treat this as an oracle. It costs nothing to close.
    process_ok = bool(expected) and bool(presented) and secrets.compare_digest(presented, expected)

    marker = _database_run_id()
    database_ok = process_ok and bool(marker) and secrets.compare_digest(presented, marker or "")

    if process_ok and database_ok:
        return {"status": "ok"}

    response.status_code = 409
    return {"status": "mismatch"}
