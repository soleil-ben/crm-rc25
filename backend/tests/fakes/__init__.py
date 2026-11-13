"""Test doubles.

Everything here is **fake** and lives under ``tests/`` so the running application cannot
import it. Nothing in this package describes a real provider, and in particular nothing
here describes ShipStation: its product, API generation, entitlements, authentication,
webhook event types, signature mechanism, rate limits, and resource hosts are all
unverified (``docs/INTEGRATIONS.md`` section 3), so a fixture claiming to represent them
would be a guess wearing the costume of a fact.
"""
