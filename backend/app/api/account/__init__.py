"""The Customer Account surface: authenticated, and authenticated as somebody who is not staff.

Everything under this package serves customers, and nothing in it may import the staff
request dependencies -- ``app.api.deps``'s session resolver, its CSRF check, its permission
factory, or its settings dependency. Importing any of them would attach a staff dependency
to a customer route, which on an *authenticated* surface produces a working session rather
than an obvious error (DEC-0090, T-01).

The same rule applies in the other direction and to the public surface: nothing here imports
``app.api.public`` either, because a shared helper between two customer-facing surfaces is a
shared helper that one of them will eventually outgrow while the other keeps depending on the
old behaviour.

This is the treatment ``app/api/public/__init__.py`` already describes for its own package,
and ``backend/tests/test_account_boundary.py`` asserts it over this package's source the same
way -- so the boundary is checked rather than merely intended.
"""
