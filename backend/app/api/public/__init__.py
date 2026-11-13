"""The public, unauthenticated surface.

Everything under this package is reachable without a staff session and must stay that
way. Nothing here may import the staff request dependencies -- the session resolver, the
CSRF check, the permission factory, or the settings dependency that returns an internal
response contract -- because importing any of them would attach a staff dependency to a
customer-facing route.

``backend/tests/test_public_tracking.py`` asserts that this package's source contains no
such import, so the boundary is checked rather than merely intended.
"""
