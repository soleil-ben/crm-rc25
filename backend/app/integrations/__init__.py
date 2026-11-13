"""Provider integration boundary (Phase 4A).

**No provider is connected, and no request has ever been made to a carrier or to
ShipStation by this application.** What lives here is the infrastructure whose
correctness does not depend on which provider is eventually chosen:

* ``adapter`` -- the narrow contract a provider integration must satisfy, expressed in
  capabilities rather than assumptions.
* ``registry`` -- the production adapter registry. Empty, and registration is refused
  while the environment is production.
* ``resource_policy`` -- HTTPS, exact host and path allowlists, DNS checks, redirect
  rules. **No network request is made.**
* ``redaction`` -- what may reach a log, an error column, or an audit row.

The rule the rest of the application depends on: **nothing outside this package imports a
provider response structure, status code, endpoint, or header name** (CRM.md section 9).
``backend/tests/test_integration_adapter.py`` asserts it by parsing the source tree rather
than trusting the convention.

The only adapter implementation is a deterministic fake, and it lives in
``backend/tests/fakes/`` so it cannot be imported by the running application.
"""
