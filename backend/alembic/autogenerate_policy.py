"""What Alembic autogeneration is allowed to ignore, and why each name is there.

``alembic check`` compares the database against ``app.models.Base.metadata`` and fails when
they differ. That is the point of it: schema drift should be loud. But one table in this
database is deliberately not in that metadata.

``role_merge_provenance`` is created, written, read and dropped entirely by the role-merge
migration ``a1c7f4d92b30``. It records the role each account held *before* the merge so the
downgrade can restore it, which is the only thing that makes that migration reversible. No
ORM model maps it and no application code touches it -- deliberately, because it holds
staff identifiers outside the access controls that protect ``users``, and a mapped model is
an invitation to read it at runtime.

Autogeneration therefore sees a table in the database with no model behind it and proposes
the one thing it can: ``DROP TABLE role_merge_provenance``. Dropping it would silently make
the role merge irreversible. Mapping it into the ORM purely to silence the check would
create the runtime handle the migration spent its design avoiding.

So the exclusion below is deliberately the narrowest shape that solves this and nothing
more:

* it names the table literally -- not a prefix, not a pattern, not "any unmapped table", so
  a second migration-owned table cannot be added later without a decision being taken here;
* it applies only to a *reflected* table that has *no* counterpart in the metadata
  (``compare_to is None``). If somebody ever does map this table, the exclusion stops
  applying to it that same moment and Alembic compares it like any other;
* it says nothing about columns, indexes or constraints on tables that *are* mapped, so
  every other kind of drift -- an added column, a changed type, a removed table -- still
  fails the check.

What it does cost, stated plainly: while a table is unmapped, drift *within* it is not
detected either, because the whole object is skipped. For ``role_merge_provenance`` the
migration is the only writer of its shape, and ``tests/test_migrations_role_merge.py``
asserts that shape column by column, which is where that guarantee lives instead. For
``e2e_run_marker`` the cost is nil: it is created by one function in
``scripts/e2e_env.py``, read by one function in ``app.api.e2e``, and lives only in a file
that is deleted when the run that made it finishes.
"""

from __future__ import annotations

from typing import Any

#: Tables owned by a migration rather than by a model. Adding a name here means "the
#: application will never map this, and autogeneration must stop proposing its removal" --
#: a decision, not a convenience.
MIGRATION_OWNED_TABLES = frozenset({"role_merge_provenance"})

#: Tables owned by the end-to-end harness. Exactly one, and it exists only inside a
#: throwaway ``.e2e.db``.
#:
#: ``scripts/e2e_env.py`` writes the run identifier into ``e2e_run_marker`` in the scratch
#: database it has just built, and ``app.api.e2e`` reads it back to prove that the backend
#: a browser reached is serving the database that run created. No migration creates it, no
#: model maps it, and it is deliberately not in either: a table that exists in every
#: database would not distinguish an E2E database from a real one, which is the entire
#: thing it is for.
#:
#: **This exclusion changes nothing about a real database.** The table cannot be present in
#: the development, UAT or production database, because only the E2E launcher creates it and
#: ``app.core.e2e_guard`` refuses to let that launcher touch any of them. What the exclusion
#: does is stop ``alembic check`` reporting drift when it is pointed at a scratch database --
#: which is exactly where it should be pointed, since checking the development database
#: means opening it.
#:
#: Same narrow shape as above: the literal name, reflected tables only, and only while
#: nothing maps it.
HARNESS_OWNED_TABLES = frozenset({"e2e_run_marker"})

#: The union the hook consults. Kept as two named sets rather than one list because the two
#: reasons are different, and a future reader deciding whether to add a third name needs to
#: know which argument they are making.
EXCLUDED_TABLES = MIGRATION_OWNED_TABLES | HARNESS_OWNED_TABLES


def include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Alembic's ``include_object`` hook. False hides an object from autogeneration only.

    Returning False here keeps the object out of the *comparison*; it has no effect on what
    migrations do. ``a1c7f4d92b30`` still creates the table on upgrade and still drops it on
    downgrade.
    """
    excluded = type_ == "table" and reflected and compare_to is None and name in EXCLUDED_TABLES
    return not excluded
