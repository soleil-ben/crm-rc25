"""Background workers.

One worker exists: ``integration_worker``. It claims jobs from the durable queue and runs
them through a provider adapter.

**No provider adapter is registered**, so a run against this installation reclaims nothing,
claims nothing, and says so. That is the correct behaviour rather than a gap: the CRM,
manual milestones, external links, bookings, labels, and public tracking all work with the
worker stopped, and a missing API key never prevents anything from starting
(CRM.md section 3).

Run one bounded pass:

```
backend/.venv/Scripts/python -m app.workers.integration_worker --once
```

Continuous mode and graceful shutdown are documented in ``docs/OPERATIONS.md``. **No
unattended service was started during this build.**
"""
